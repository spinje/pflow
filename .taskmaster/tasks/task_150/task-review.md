# Task 150 Review: Wire WorkflowValidator into Save Path

## Metadata

- Implementation Date: 2026-04-10
- GitHub Issue: spinje/pflow#236
- Branch: `fix/fix-pflow-workflow-save-validator`
- Related: Task 147 (validator produces Diagnostics — filed #236 as incurred debt), Task 144 ("delete the bypass" pattern)

## Executive Summary

Made `save_workflow_with_options` own parse + validate + save as one atomic operation. CLI and MCP save paths now run the full 9-step `WorkflowValidator` — the same validation as `--validate-only` and `pflow run`. Deleted 2 CLI helper functions (`_load_and_parse_workflow`, `_save_with_overwrite_check`), simplified MCP `ExecutionService.save_workflow`, and added 3 tests (CLI rich diagnostics, MCP rich diagnostics, force-save ordering invariant). 12 files changed, net ~100 lines deleted from production code.

## Implementation Overview

### What Was Built

`save_workflow_with_options()` in `save_service.py` gained two lines of actual logic at the top — `parse_markdown(markdown_content)` and `_validate_and_normalize_ir(result.ir, ...)` — plus a return-type expansion from `tuple[Path, list[str]]` to `tuple[Path, list[str], dict[str, Any]]`. Everything else was deletion and simplification of callers.

### Deviations from Plan

| Deviation | Why |
|-----------|-----|
| Added `except (WorkflowValidationError, MarkdownParseError): raise` to `_save_and_format_result` | Bug found during code review: the generic `except Exception` would swallow validation errors before `save_workflow` could render them with rich diagnostics. The plan's simplified `_save_and_format_result` didn't account for this. |
| Added MCP regression test (`TestWorkflowSaveRichDiagnostics`) | Code review suggestion — without it, the exception-swallowing bug above had no test coverage. Existing MCP tests use loose `ValueError` pattern matching that passes regardless. |
| Added ordering invariant test (`test_force_save_invalid_content_preserves_existing`) | Not in the plan. Identified during "high value test" analysis: if validation is moved after the existence check, `--force` with invalid content deletes the existing workflow before failing. |

### Spec Assumptions That Were Wrong

- **The plan assumed `_save_and_format_result` could be simplified to no error handling.** In reality, the existing `except Exception` catch was load-bearing for non-validation errors (I/O failures from `format_save_success`, `manager.save()` exceptions). Removing the `WorkflowValidationError` catch was correct; removing ALL catches would have let unexpected errors propagate as raw exceptions to the MCP tool layer.

## Files Modified/Created

### Core Changes (4 production files)

- `src/pflow/core/workflow/save_service.py` — 2 lines of logic added: `parse_markdown` + `_validate_and_normalize_ir` at top of `save_workflow_with_options`. Return type expanded. Docstring updated. Both `parse_markdown` and `_validate_and_normalize_ir` were already available in the same file (imported/defined).
- `src/pflow/cli/commands/workflow.py` — Deleted `_load_and_parse_workflow` (49 lines) and `_save_with_overwrite_check` (48 lines). Rewrote `save_workflow` Click command as a single try/except flow. Rich diagnostic display via `format_validation_failure()` when `e.validation_errors` is populated, matching `--validate-only` output.
- `src/pflow/mcp_server/services/execution_service.py` — Deleted manual `parse_markdown` + `load_and_validate_workflow` block from `save_workflow`. Removed `workflow_ir` parameter from `_save_and_format_result`. Added `except (WorkflowValidationError, MarkdownParseError): raise` before the generic catch.
- 3 CLAUDE.md files updated to reflect the new ownership model.

### Test Files (4 files, 3 new tests)

| Test | What it guards |
|------|---------------|
| `test_workflow_save_cli.py::test_workflow_save_renders_rich_validation_diagnostics` | Core #236 regression — CLI save rejects unknown params with numbered diagnostic format |
| `test_workflow_save_cli.py::test_force_save_invalid_content_preserves_existing` | Ordering invariant — validation before deletion prevents data loss on force-save of broken content |
| `test_workflow_save.py::test_unknown_param_produces_rich_diagnostic` | MCP parity — structured diagnostics survive the three-layer exception chain |
| All `test_workflow_save_service.py::TestSaveWorkflowWithOptions` (7 tests) | Return type unpacking + validated IR assertions |
| All `test_workflow_bundling.py` (4 unpack sites + 1 assertion update) | Bundling still works after return type change; sub-workflow validation fires before file-ref guard |

## Architectural Decisions & Tradeoffs

### Key Decisions

**"Validation inside save" over "validation in caller"** — The GH issue proposed patching the CLI caller. We chose to move validation into `save_workflow_with_options` itself so the precondition is enforced by the API, not trusted from callers. This is the Task 144 pattern: "delete the bypass, bring behavior into the unified pipeline." Two callers (CLI, MCP) each had their own "prepare for save" logic; one forgot to validate.

**3-tuple return instead of `SaveResult` dataclass** — A dataclass was considered but adds a new type for 3 fields. The tuple expansion touches 10+ unpack sites, but each change is mechanical. If the return grows further, a dataclass should be introduced.

**`WorkflowValidationError` dual semantics preserved** — `save_workflow_with_options` raises `WorkflowValidationError` for two different reasons: validation failures (has `validation_errors` list) and save-mechanic failures (summary string only). CLI distinguishes them via `e.validation_errors` check. This is pre-existing and works, but is a design smell — a future cleanup could use distinct exception types.

### Technical Debt

| Item | Notes |
|------|-------|
| `load_and_validate_workflow` has zero production callers | MCP save was its last caller. Still useful as public API and exercised by tests. |
| Triple `parse_markdown` on save-with-bundling | `save_workflow_with_options` parses, then `_discover_and_bundle_deps` parses again, then `_reject_unbundleable_file_refs` may parse a third time. Pre-existing double-parse; now triple. Not a correctness issue. |
| #247 exposure expanded | CLI save now gets the same false positive on `${input.field}` in output sources that MCP save and `--validate-only` already have. Correct behavior — the validator is applied consistently. #247 should be fixed separately. |

## Unexpected Discoveries

### The Exception Swallowing Bug

The plan's simplified `_save_and_format_result` (remove `workflow_ir` param, remove error handling) would have introduced a regression: the remaining generic `except Exception` catches `WorkflowValidationError` before `save_workflow` can render it with `format_validation_failure`. The MCP agent would get `"Failed to save workflow: Invalid workflow 'X' - Validation errors:..."` instead of the numbered diagnostic format. Existing MCP tests didn't catch this because they assert on `match=r"Invalid|Unknown"` which matches both.

**Lesson**: When simplifying a function's error handling, verify that every exception type in the inner function's contract either (a) is caught explicitly or (b) propagates correctly through all intermediate layers. Three-layer exception chains are especially prone to this.

### Validation Ordering Changes Bundling Test Behavior

`test_raw_content_with_sub_workflow_ref_rejected` relied on `_reject_unbundleable_file_refs` catching sub-workflow file references before validation. After the change, the validator's step 8 (sub-workflow validation) fires first with `"Cannot resolve relative sub-workflow"` — a more specific error caught earlier. The behavior is strictly better, but the test assertion had to change.

### The Review Process Caught Real Issues

All 3 review agents independently found the missing `test_workflow_bundling.py` — a file with 6 `save_workflow_with_options` calls that would have broken on the return-type change. This was a genuine miss in the plan, not a theoretical concern. The convergent signal across independent agents was strong evidence.

## Patterns Established

### "The save function owns its validation"

When a function persists data, validation belongs inside the function, not in the caller. This eliminates the "precondition not enforced by API" bug class. The pattern:

```python
def save_something(content: str, ...) -> SaveResult:
    parsed = parse(content)          # Parse
    validated = validate(parsed)      # Validate (raises on failure)
    result = persist(content, ...)    # Save original content
    return SaveResult(..., validated) # Return validated data for display
```

Callers never pre-validate. The function is the trust boundary.

### Exception propagation in layered MCP services

When an MCP service method delegates to a helper that has a generic `except Exception`, validation/parse errors must be explicitly re-raised before the generic catch:

```python
# In the helper (_save_and_format_result)
except (WorkflowValidationError, MarkdownParseError):
    raise  # Let caller handle with rich rendering
except Exception as e:
    raise ValueError(f"Failed: {e}") from e  # Wrap unexpected errors
```

### Ordering invariant test for data-safety

When a function does "validate then delete then save", test that validation failure prevents deletion:

```python
def test_force_save_invalid_content_preserves_existing(...):
    # Save valid workflow
    # Try to force-save invalid content
    assert exit_code != 0
    assert existing.exists(), "Valid workflow was deleted before validation caught the error"
    assert existing.read_text() == original_content
```

## AI Agent Guidance

### Quick Start for Related Tasks

1. Read `src/pflow/core/workflow/save_service.py:353-430` — `save_workflow_with_options` is the save-time trust boundary
2. Read `src/pflow/mcp_server/services/execution_service.py:304-415` — the three-layer exception chain: `save_workflow` → `_save_and_format_result` → `save_workflow_with_options`
3. Read `src/pflow/cli/commands/workflow.py:255-330` — the CLI save command's error handler, especially the `e.validation_errors` check

### Common Pitfalls

- **Don't add pre-validation in callers of `save_workflow_with_options`** — the function validates internally. Caller pre-validation is redundant and risks drift.
- **Don't reorder `_save_and_format_result`'s exception handlers** — `(WorkflowValidationError, MarkdownParseError)` must come before `Exception`, or rich diagnostics are lost.
- **Don't move validation after the existence check in `save_workflow_with_options`** — force-save of invalid content would delete the existing workflow before failing. The `test_force_save_invalid_content_preserves_existing` test guards this.
- **`WorkflowValidationError` with `validation_errors` vs without** — validation failures populate `validation_errors` (list of Diagnostics). Save-mechanic failures (delete error, I/O error) only have a summary string. CLI/MCP error handlers must check `e.validation_errors` before calling `format_validation_failure`.

### Test-First Recommendations

When modifying save path code, run these first:
```bash
pytest tests/test_core/test_workflow_save_service.py tests/test_cli/test_workflow_save_cli.py tests/test_mcp_server/test_workflow_save.py tests/test_integration/test_workflow_bundling.py -v
```

---

*Generated from implementation context of Task 150*
