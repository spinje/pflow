# Task 144: Display Consolidation — Eliminate Diagnostic Dict Round-Trips

## Description

Eliminate the Diagnostic-to-dict-to-Diagnostic round-trip pattern left over from Task 143's transition strategy. All text rendering paths should operate on `Diagnostic` objects natively via `format_diagnostic()`, removing the `coerce_*_diagnostic()` bridges and the intermediate dict serialization for text consumers.

## Status

not started

## Priority

medium

## Problem

Task 143 introduced a unified `Diagnostic` type that replaced all ad-hoc warning/error types. The implementation correctly uses `Diagnostic` as the primary storage on `ExecutionResult` and `ValidationResult`. However, several display paths still round-trip through dicts:

**The dict round-trip anti-pattern (3 paths):**

```
Diagnostic → to_display_dict() → dict → coerce_*_diagnostic() → Diagnostic → format_diagnostic() → text
```

This exists because `format_execution_success()` serves both JSON and text consumers but only produces a dict. Text consumers then reconstruct Diagnostics from that dict.

Affected paths:
1. **CLI text success** — `_display_execution_summary()` at `workflow_output.py:600` coerces warnings back from display dicts
2. **MCP text success** — `format_success_as_text()` at `success_formatter.py:249` does the same round-trip
3. **MCP text failure errors** — `_build_error_text()` at `execution_service.py:163` coerces errors back from display dicts

**The validation error degradation (2 paths):**

`ValidationResult.errors` returns `list[str]` (just messages), losing `suggestion`, `node_id`, `source`, and `context`. Two consumers use this degraded form:
1. `format_validation_failure(vresult.errors)` — renders bullet-point strings, losing fix suggestions
2. `_display_validation_result()` JSON mode — hand-crafts `{"message": e, "category": "validation"}` dicts that have a different shape from `to_display_dict()` output

**Duplicate bridge functions (7 call sites):**

`coerce_warning_diagnostic()` (5 sites) and `coerce_error_diagnostic()` (2 sites) exist solely because display code receives dicts instead of Diagnostics. These are dead code once all text paths receive Diagnostics natively.

**Mixed types in MCP error path:**

`_format_error_result()` puts raw `Diagnostic` objects in `error_dict["warnings"]` but display dicts in `error_dict["errors"]` — a footgun for future consumers.

## Solution

Split `format_execution_success()` to serve JSON and text consumers separately. Text consumers receive `Diagnostic` objects directly; JSON consumers receive serialized dicts. This eliminates the round-trip and the need for `coerce_*_diagnostic()`.

High-level approach:
1. **Split the success formatter** — `format_execution_success()` continues to return the JSON-ready dict. Add a parallel text-rendering path that accepts `list[Diagnostic]` directly.
2. **Update `ValidationResult.errors`** to return `list[Diagnostic]` and update `format_validation_failure()` to accept Diagnostics.
3. **Remove `coerce_warning_diagnostic()` and `coerce_error_diagnostic()`** from `diagnostic.py` — all callers updated to receive Diagnostics natively.
4. **Normalize the MCP error path** — `_format_error_result()` and `_build_error_text()` receive Diagnostics directly instead of mixed types.

## Design Decisions

- **`format_execution_success()` keeps its dict return type**: JSON consumers (CLI JSON, MCP JSON) need serialized dicts. Don't change the JSON contract. The change is that text consumers no longer go through this function's output — they receive Diagnostics directly from the caller.
- **`ValidationResult.errors` changes to `list[Diagnostic]`**: This was deferred from Task 143 because `format_validation_failure()` took `list[str]`. Now we change both together. An `error_messages` property provides the `list[str]` shortcut if needed.
- **`to_display_dict()` stays for JSON serialization**: The flat-dict-with-context-merged shape is the JSON wire format. `to_display_dict()` is the serializer for that format. It's not a bridge — it's the JSON contract. What gets removed is the pattern of deserializing those dicts back into Diagnostics for text rendering.
- **`to_dict()` stays for the `diagnostics` key**: The `diagnostics` key in JSON output uses the canonical nested-context shape. This is permanent, not transitional.

## Dependencies

- Task 143: Unified Diagnostic System — must be merged first. This task is the follow-up consolidation.

## Requirements

### Text Rendering Paths

All text rendering paths must receive `Diagnostic` objects directly and call `format_diagnostic()` without any intermediate dict conversion:

- CLI text success warnings: `_display_execution_summary()` receives `list[Diagnostic]`, not display dicts
- MCP text success warnings: `format_success_as_text()` receives `list[Diagnostic]`, not display dicts
- MCP text failure errors: `_build_error_text()` receives `list[Diagnostic]`, not display dicts
- MCP text failure warnings: already receives Diagnostics (no change needed)
- CLI text failure: already receives Diagnostics (no change needed)
- CLI text exception: already receives Diagnostics (no change needed)

### Validation Result

- `ValidationResult.errors` returns `list[Diagnostic]` (not `list[str]`)
- `format_validation_failure()` accepts `list[Diagnostic]` and renders message + suggestion + path from each
- `_display_validation_result()` JSON mode uses `to_display_dict()` for errors (not hand-crafted dicts)
- MCP `validate_workflow()` uses Diagnostics for errors (not degraded strings)

### Bridge Function Removal

- `coerce_warning_diagnostic()` deleted from `diagnostic.py` — all 5 call sites updated
- `coerce_error_diagnostic()` deleted from `diagnostic.py` — all 2 call sites updated
- No caller in `src/` should need to convert dict→Diagnostic for display

### JSON Output Unchanged

- `format_execution_success()` return shape stays the same (dict with `warnings`, `diagnostics` keys)
- `format_error_json()` return shape stays the same
- `to_display_dict()` and `to_dict()` stay — they serve JSON serialization, not text rendering

### MCP Error Path Consistency

- `_format_error_result()` returns consistent types — both errors and warnings as the same type (either both Diagnostics or both dicts, not mixed)
- `_build_error_text()` receives Diagnostics directly for both errors and warnings

## Implementation Notes

### Current call sites to change

**`coerce_warning_diagnostic` (5 production sites — all become unnecessary):**
1. `success_formatter.py:57` — coerces in `format_execution_success()`, stays for JSON but text path bypasses
2. `success_formatter.py:249` — `format_success_as_text()` round-trip, receives Diagnostics directly instead
3. `workflow_output.py:600` — `_display_execution_summary()` round-trip, receives Diagnostics directly instead
4. `workflow_errors.py:108` — `_extract_result_warnings()` fallback, no longer needed when result always has Diagnostics
5. `execution_service.py:171` — `_build_error_text()` receives Diagnostics directly instead

**`coerce_error_diagnostic` (2 production sites):**
1. `execution_service.py:163` — `_build_error_text()` receives Diagnostics directly instead
2. `workflow_errors.py:40` — `_display_single_error()` already receives Diagnostics from `result.errors` property, coerce becomes passthrough-only (defensive)

### How the success text path changes

Currently:
```
_handle_workflow_success → format_execution_success(warnings=Diagnostics) → dict with warnings as display_dicts
→ _display_execution_summary(dict) → reads dict["warnings"] → coerce back → format_diagnostic
```

After:
```
_handle_workflow_success → format_execution_success(warnings=Diagnostics) → dict (for JSON only)
                         ↘ _display_execution_summary(diagnostics=Diagnostics) → format_diagnostic directly
```

The key change: `_display_execution_summary()` and `format_success_as_text()` receive `list[Diagnostic]` as a separate parameter instead of extracting warnings from the formatted success dict.

### How `format_validation_failure()` changes

Currently: `format_validation_failure(errors: list[str], suggestions: list[str] | None)` — renders bullet points from plain strings.

After: `format_validation_failure(errors: list[Diagnostic])` — renders using `format_diagnostic()` for each error. Suggestions come from `Diagnostic.suggestion`. The `suggestions` parameter is removed (suggestions are INFO diagnostics in `vresult.diagnostics`, rendered separately).

### Files to modify

| File | Change |
|------|--------|
| `src/pflow/core/diagnostic.py` | Delete `coerce_warning_diagnostic()` and `coerce_error_diagnostic()` |
| `src/pflow/execution/result.py` | `ValidationResult.errors` returns `list[Diagnostic]`, add `error_messages -> list[str]` property |
| `src/pflow/execution/formatters/success_formatter.py` | `format_success_as_text()` takes `list[Diagnostic]` for warnings, not extracted from dict |
| `src/pflow/execution/formatters/validation_formatter.py` | `format_validation_failure()` takes `list[Diagnostic]` |
| `src/pflow/cli/workflow_output.py` | `_display_execution_summary()` takes `list[Diagnostic]` for warnings |
| `src/pflow/cli/workflow_errors.py` | Remove `_extract_result_warnings()` dict fallback, remove coerce calls |
| `src/pflow/cli/main.py` | `_display_validation_result()` uses Diagnostics for errors and warnings in JSON |
| `src/pflow/mcp_server/services/execution_service.py` | `_format_error_result()` and `_build_error_text()` use Diagnostics consistently |

### What NOT to change

- `format_execution_success()` return type (dict) — JSON consumers depend on it
- `to_display_dict()` / `to_dict()` — these are JSON serializers, not bridges
- `exception_to_diagnostics()` — already clean
- `format_diagnostic()` — already the canonical text renderer
- `build_error_list()` in `executor_service.py` — already returns `list[Diagnostic]`

### Open question: `format_success_as_text()` architecture

`format_success_as_text()` currently converts a success dict (from `format_execution_success()`) to text. After this task, it needs Diagnostics for warning rendering but still needs the dict for execution steps, metrics, etc.

Two options:
1. **Pass Diagnostics alongside the dict**: `format_success_as_text(success_dict, warnings=list[Diagnostic])` — simple, minimal change
2. **Replace `format_success_as_text()` with a function that takes native types**: would require passing `ExecutionResult` or its components directly — larger refactor

**Needs decision before implementation.** Option 1 is pragmatic and avoids a larger restructuring. Option 2 is cleaner but may be too much scope for one task.

### Open question: `_display_execution_summary()` receives warnings how?

Currently `_display_execution_summary(formatted_result: dict)` extracts `formatted_result.get("warnings", [])`. The warnings need to be Diagnostics.

Options:
1. **Add a `warning_diagnostics` parameter**: `_display_execution_summary(formatted_result, warning_diagnostics=list[Diagnostic])` — caller passes both
2. **Put Diagnostics in the formatted_result dict**: `formatted_result["warning_diagnostics"] = list[Diagnostic]` alongside the serialized `"warnings"` key — this mixes types in the dict but is minimal change

**Needs decision before implementation.**

## Verification

### Functional
- All text output paths render warnings via `format_diagnostic()` without any dict→Diagnostic coercion step
- Validation text output shows suggestions from Diagnostics (currently lost for error-level diagnostics)
- Validation JSON output uses `to_display_dict()` for errors (consistent shape with execution errors)
- MCP error text renders both errors and warnings consistently (no mixed types in intermediate dict)
- `coerce_warning_diagnostic` and `coerce_error_diagnostic` are absent from the codebase

### Non-regression
- `make test` passes (4500+ tests)
- `make check` passes
- CLI text/JSON output shape unchanged from Task 143 (diff baselines)
- MCP text output shape unchanged
- Validation output shows at least as much information as before (more, because error suggestions now visible)

### Edge cases
- Workflow with no warnings — `warnings` key in JSON is empty list, not absent
- Workflow with only parser warnings — text shows warnings, status is SUCCESS (not DEGRADED)
- Validate-only with errors + suggestions — both render in text and JSON

## References

- Task 143: Unified Diagnostic System — the predecessor that introduced `Diagnostic`
- Task 143 implementation: `src/pflow/core/diagnostic.py` (the type, bridge functions, formatter)
- Task 143 progress log: `.taskmaster/tasks/task_143/implementation/progress-log.md`
- Audit of all display paths: performed in the Task 143 review conversation (2026-04-04), findings summarized in the Problem section above
- Current bridge call sites: `coerce_warning_diagnostic` (5 sites), `coerce_error_diagnostic` (2 sites) — exact locations in Implementation Notes

### Key files (current state)
- `src/pflow/core/diagnostic.py` — bridge functions to delete
- `src/pflow/execution/result.py:46` — `ValidationResult.errors` property to change
- `src/pflow/execution/formatters/success_formatter.py:56-60, 249` — the round-trip pattern
- `src/pflow/execution/formatters/validation_formatter.py:40-104` — takes `list[str]`, needs `list[Diagnostic]`
- `src/pflow/cli/workflow_output.py:600` — the round-trip pattern
- `src/pflow/mcp_server/services/execution_service.py:137-177` — mixed types in error path
