# Task 150: Wire WorkflowValidator into Save Path

## Description

`pflow workflow save` bypasses `WorkflowValidator.validate()` entirely — broken workflows silently enter the library and only fail at run time. Fix by making `save_workflow_with_options` own parse + validate + save as one atomic operation, eliminating the bypass class.

## Status

not started

## Priority

high

## Problem

`save_workflow_with_options` trusts callers to pre-validate. Two callers (CLI, MCP) each implemented their own "prepare for save" logic. The MCP path correctly calls `load_and_validate_workflow` (full 9-step validator). The CLI path's `_load_and_parse_workflow` only calls `validate_ir` (schema-only). Result: unknown params, non-existent node refs, template errors, and broken sub-workflows are all accepted by `pflow workflow save` without complaint.

Same bug class as GH #66 (pre-execution validation weaker than `--validate-only`), which was fixed for the run path but never addressed for save.

Additionally, Task 147's error filter at `save_service.py:139` (the `Severity.ERROR` filter on validator diagnostics) is effectively dead code from the CLI surface — only reachable from the MCP path.

## Solution

Apply the Task 144 pattern: "delete the bypass, bring behavior into the unified pipeline."

Move parse + validate into `save_workflow_with_options` itself. Callers pass raw markdown content; the function parses, validates via `_validate_and_normalize_ir` (which already exists in the same file), and saves. Return type expands to include the validated IR (callers need it for the success formatter).

This deletes 2 CLI helper functions (`_load_and_parse_workflow`, `_save_with_overwrite_check`), simplifies the MCP save method, and makes it structurally impossible to save without validating.

## Design Decisions

- **Validation inside save, not patched in callers**: Options A/B/C (adding validation to the CLI caller) would fix this instance but leave the precondition unenforced. A third caller next month could make the same mistake. Option D (save owns validation) eliminates the bug class.
- **Return type expands to 3-tuple, not a dataclass**: `tuple[Path, list[str], dict[str, Any]]` adds the validated IR. A `SaveResult` dataclass was considered but adds a new type for 3 fields — marginal benefit. Can be introduced later if the tuple grows further.
- **`MarkdownParseError` propagates unchanged**: Both CLI and MCP already handle it. No wrapping needed.
- **Rich diagnostic display for CLI save errors**: Uses `format_validation_failure()` — the same renderer as `--validate-only` — matching the acceptance criteria from GH #236.
- **JSON rejection stays in CLI command**: It's a CLI-specific migration message, not a validation concern.

## Dependencies

None. All prerequisite infrastructure exists:
- `_validate_and_normalize_ir` (save_service.py:83) — the shared validation core
- `WorkflowValidator.validate()` returning `list[Diagnostic]` (Task 147)
- `format_validation_failure()` (Task 144) — the rich error renderer

## Requirements

### Validation Parity
- `pflow workflow save` rejects the same broken workflows that `--validate-only` and `pflow run` reject
- Error output uses the same `format_validation_failure` renderer as `--validate-only` (numbered format with suggestions)
- Valid workflows continue to save successfully

### API Contract
- `save_workflow_with_options` returns `tuple[Path, list[str], dict[str, Any]]` (path, bundled_files, validated_ir)
- `save_workflow_with_options` can now raise `MarkdownParseError` (new) and `WorkflowValidationError` with `validation_errors` populated (new), in addition to existing exceptions
- `WorkflowValidationError` from validation (has `validation_errors`) vs from save mechanics (summary-only) must be distinguishable by callers via `e.validation_errors`

### Cleanup
- `_load_and_parse_workflow` deleted from `workflow.py`
- `_save_with_overwrite_check` deleted from `workflow.py`
- MCP's manual `parse_markdown` + `load_and_validate_workflow` block deleted from `execution_service.py`

## Implementation Notes

**Validation ordering interaction**: Validation now runs BEFORE `_reject_unbundleable_file_refs` and `_discover_and_bundle_deps`. One bundling test (`test_raw_content_with_sub_workflow_ref_rejected`) relies on hitting the file-ref guard before validation. After the change, the sub-workflow validator (step 8) catches it first with a different error message. The test assertion needs updating — the behavior is actually better (more specific error, caught earlier).

**#247 exposure change**: CLI save previously didn't run the validator, so it couldn't hit #247 (false positive on `${input.field}` in output sources). After this fix, CLI save gains the same #247 exposure that MCP save and `--validate-only` already have. Correct behavior — #247 should be fixed separately.

**`load_and_validate_workflow` becomes test-only**: Loses its last production caller (MCP save) after this change. Still useful as public API and exercised by tests.

**Double parse**: `save_workflow_with_options` will parse markdown (new), then `_discover_and_bundle_deps` parses it again internally. Pre-existing pattern (the old code also double-parsed). Not worth fixing in this PR.

## Verification

1. **Reproduce GH #236**: `pflow workflow save /tmp/broken.pflow.md --name test-broken` with unknown param `file_pat` — must fail with rich diagnostic showing "Unknown parameter" and "file_pat"
2. **Parity check**: Compare save error output with `pflow /tmp/broken.pflow.md --validate-only` — same diagnostic format
3. **Valid save**: `pflow workflow save /tmp/valid.pflow.md --name test-valid` — still succeeds
4. **Targeted test suite**: `test_workflow_save_service.py`, `test_workflow_save_cli.py`, `test_workflow_save.py` (MCP), `test_workflow_bundling.py`, `test_validate_only.py` (regression)
5. **Full suite**: `make test` + `make check`

## References

- **GH Issue**: spinje/pflow#236
- **Implementation plan**: `.taskmaster/tasks/task_150/implementation/implementation-plan.md`
- **Prior art (same pattern)**: Task 144 review — "delete the bypass, bring behavior into the unified pipeline"
- **Task 147 review**: `.taskmaster/tasks/task_147/task-review.md` line 217 — filed #236 as incurred debt
- **Key files**: `src/pflow/core/workflow/save_service.py`, `src/pflow/cli/commands/workflow.py`, `src/pflow/mcp_server/services/execution_service.py`
