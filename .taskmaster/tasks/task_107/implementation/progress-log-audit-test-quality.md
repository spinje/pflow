# Test Quality Audit — Task 107 Migration

## Summary
- Files audited: 38
- Files with concerns: 5
- Files clean: 33
- Net test count change: -24 (but -21 are intentional replacements, -6 are feature removal)

## Test Count Comparison

| File | Main | Current | Delta | Notes |
|------|------|---------|-------|-------|
| test_cli/test_main.py | 30 | 30 | 0 | Clean — .json -> .pflow.md string swaps |
| test_cli/test_workflow_save.py | 9 | 9 | 0 | Clean |
| test_cli/test_workflow_save_cli.py | 12 | 12 | 0 | Clean |
| test_cli/test_workflow_save_integration.py | 7 | 6 | -1 | `test_save_workflow_validates_names_with_real_filesystem` removed — see concerns |
| test_cli/test_validate_only.py | 11 | 12 | +1 | Added `test_validate_only_rejects_json_files` |
| test_cli/test_dual_mode_stdin.py | 22 | 22 | 0 | Clean |
| test_cli/test_enhanced_error_output.py | 9 | 9 | 0 | Clean — no assertion changes |
| test_cli/test_shell_stderr_warnings.py | 16 | 16 | 0 | Clean — no assertion changes |
| test_cli/test_shell_stderr_display.py | 4 | 4 | 0 | Clean — no assertion changes |
| test_cli/test_workflow_output_handling.py | 24 | 24 | 0 | Clean — no assertion changes |
| test_cli/test_workflow_output_source_simple.py | 5 | 5 | 0 | Clean — no assertion changes |
| test_cli/test_workflow_resolution.py | 37 | 35 | -2 | See concerns |
| test_cli/test_validation_before_execution.py | 5 | 5 | 0 | Clean |
| test_cli/test_planner_input_validation.py | 15 | 15 | 0 | Clean |
| test_cli/test_parse_error_handling.py (NEW) | 0 | 9 | +9 | Replaces test_json_error_handling.py (6 tests) |
| test_cli/test_json_error_handling.py (DELETED) | 6 | 0 | -6 | Replaced by test_parse_error_handling.py (+3 net) |
| test_integration/test_e2e_workflow.py | 12 | 12 | 0 | Clean |
| test_integration/test_workflow_manager_integration.py | 19 | 19 | 0 | Clean — assertions adapted correctly |
| test_integration/test_sigpipe_regression.py | 7 | 7 | 0 | Clean — no assertion changes |
| test_integration/test_metrics_integration.py | 17 | 17 | 0 | Clean |
| test_integration/test_workflow_outputs_namespaced.py | 3 | 3 | 0 | Clean |
| test_integration/test_context_builder_integration.py | 12 | 12 | 0 | Clean |
| test_integration/test_context_builder_performance.py | 8 | 8 | 0 | Clean |
| test_core/test_workflow_manager.py | 26 | 26 | 0 | Clean — assertions properly adapted |
| test_core/test_ir_schema.py | 57 | 57 | 0 | Clean — trivial changes only |
| test_core/test_ir_schema_output_suggestions.py | 3 | 3 | 0 | Clean |
| test_core/test_json_string_template_validation.py | 30 | 9 | -21 | Intentional — see analysis |
| test_core/test_stdin_no_hang.py | 8 | 8 | 0 | Clean — no assertion changes |
| test_core/test_workflow_manager_update_ir.py | 9 | 9 | 0 | Clean |
| test_core/test_workflow_save_service.py | 37 | 37 | 0 | Clean — assertions adapted |
| test_core/test_ir_examples.py | 13 | 17 | +4 | Good — expanded invalid example coverage |
| test_docs/test_example_validation.py | 3 | 3 | 0 | Clean — properly rewritten |
| test_execution/formatters/test_history_formatter.py | 29 | 29 | 0 | Clean |
| test_execution/test_executor_service.py | 12 | 12 | 0 | Clean — assertions adapted |
| test_mcp_server/test_workflow_save.py | 11 | 11 | 0 | Clean — trivial Unicode escaping fix |
| test_runtime/test_workflow_executor/test_integration.py | 7 | 7 | 0 | Clean |
| test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py | 26 | 26 | 0 | Clean |
| test_runtime/test_workflow_executor/test_workflow_name.py | 9 | 9 | 0 | See concerns |
| test_nodes/test_shell_smart_handling.py | 11 | 11 | 0 | Clean — no assertion changes |
| test_nodes/test_claude/test_claude_code.py | 47 | 41 | -6 | Intentional — see analysis |

## Analysis of Intentional Removals

### test_core/test_json_string_template_validation.py — -21 tests — INTENTIONAL, CLEAN

The entire file was **rewritten** from testing JSON string template anti-pattern detection (layer 7 validation: `_check_json_string_with_template` and `_build_param_type_map`) to testing unknown parameter warning detection (`_validate_unknown_params`). This is correct because:

- The JSON string template anti-pattern (e.g., `"body_schema": "{\"content\": \"${var}\"}"`) is no longer relevant in markdown format — you can't accidentally create escaped JSON strings in YAML/markdown
- The production code for `_check_json_string_with_template` and `_build_param_type_map` was removed
- The 9 replacement tests cover the new `_validate_unknown_params` functionality thoroughly (known params, unknown params, typo suggestions, multiple nodes, no params, unknown node types, integration through `validate()`)

**Verdict**: Clean replacement. No coverage loss.

### test_nodes/test_claude/test_claude_code.py — -6 tests — INTENTIONAL, CLEAN

Six `disallowed_tools` tests were removed. Verified that the `disallowed_tools` feature was also removed from production code (`src/pflow/nodes/claude/`) — `grep -r "disallowed_tools" src/pflow/nodes/claude/` returns no results.

**Verdict**: Clean removal. Tests deleted because feature was removed.

### test_cli/test_json_error_handling.py — -6 tests, replaced by +9 in test_parse_error_handling.py — CLEAN

The old file tested JSON syntax error handling (malformed JSON, trailing commas, JSON arrays, etc.). The new file tests markdown parse error handling (missing steps, missing type, invalid YAML, unclosed code blocks, etc.). Net gain of +3 tests with equivalent error-path coverage for the new format. Also includes `test_json_file_shows_migration_message` which tests the backwards-compatibility error message.

**Verdict**: Clean replacement with improved coverage.

## Concerns

### 1. test_cli/test_workflow_resolution.py — Severity: MEDIUM

**Tests removed (2):**
- `test_resolve_file_with_ir_wrapper` — tested resolution of wrapped format (`{"name": "test", "ir": {...}}`). This format no longer exists in markdown world, so removal is justified. However, `resolve_workflow` in main.py still has `metadata = {"ir": workflow_ir}` at line 3354 — the wrapper concept may still be partially live. Worth verifying that no code path produces wrapper-format files anymore.
- `test_invalid_json_in_file` → replaced by `test_invalid_markdown_in_file` — clean replacement
- `test_file_without_workflow_structure` — this edge case (valid file, not a workflow) was dropped. The markdown format has a much stricter parse, so a non-workflow file would fail at parse time — covered by `test_invalid_markdown_in_file`.

**Assertions weakened (3 instances):**
- `assert workflow_ir == workflow_data` changed to `assert workflow_ir is not None` in 3 places (`test_resolve_file_path_with_slash`, `test_resolve_file_path_relative`, `test_resolve_with_home_expansion`). The original assertion verified the exact IR content was preserved through the resolution pipeline. The new assertion only checks non-None. This is because markdown parse -> IR is not a lossless round-trip (normalization adds fields, parser may reorder), but the test should at minimum check key structural properties.

**Recommendation:**
- The `assert workflow_ir is not None` assertions should be strengthened to at least check `assert "nodes" in workflow_ir` or `assert len(workflow_ir["nodes"]) > 0` to verify the IR was actually parsed from the file and not just a truthy value.

### 2. test_cli/test_workflow_save_integration.py — Severity: LOW

**Test removed (1):**
- `test_save_workflow_validates_names_with_real_filesystem` — tested that `_prompt_workflow_save` rejects names with `/` characters. The test was tightly coupled to `_prompt_workflow_save` which is now gated (planner path disabled). The underlying validation (WorkflowManager rejecting invalid names) is still tested in `test_core/test_workflow_manager.py`.

**Other changes:**
- The remaining tests were simplified to test WorkflowManager directly instead of going through `_prompt_workflow_save` (which is gated). This is a correct adaptation — testing the integration point that's actually reachable.
- `test_save_workflow_handles_duplicate_names_correctly` no longer tests the "retry" flow (because `_prompt_workflow_save` is gated), but still verifies the duplicate detection and content preservation.

**Verdict**: Acceptable. The removed test's behavior is covered elsewhere.

### 3. test_cli/test_main.py — Severity: LOW

**Assertion slightly weakened (1 instance):**
- Empty file test: `assert "Invalid JSON syntax" in result.output or "JSON" in result.output` changed to `assert "steps" in result.output.lower() or "error" in result.output.lower()`. The new assertion is broader (any "error" matches) but this is testing error output messaging, not core logic. The important assertion (`assert result.exit_code != 0`) is preserved.

**Verdict**: Acceptable but slightly loose. Could be tightened to check for specific parse error messages.

### 4. test_cli/test_workflow_save_cli.py — Severity: LOW

**Assertions adapted (structural check changes):**
- Old: `assert saved_data["ir"]["nodes"][0]["id"] == "test"` (parsed JSON, checked IR inside wrapper)
- New: `assert "### test" in content` (checks markdown heading for node ID)
- Old: `assert "ir_version" in saved_data["ir"]` and `assert "edges" in saved_data["ir"]`
- New: `assert saved_file.exists()` (just existence check for auto-normalization test)

The auto-normalization test (`test_workflow_save_auto_normalizes`) no longer verifies that `ir_version` and `edges` are actually added after save. It only checks the file exists. This is weaker but the normalization is tested in `test_core/test_ir_schema.py` and `test_core/test_workflow_manager.py`.

**Recommendation**: Consider adding an assertion in the auto-normalization test that reads back the saved file and verifies it contains the expected steps/nodes.

### 5. test_runtime/test_workflow_executor/test_workflow_name.py — Severity: LOW

**Assertions adapted:**
- `assert prep_res["workflow_ir"] == simple_workflow_ir` changed to individual field checks: `assert loaded_ir["nodes"][0]["id"] == ...`, `assert loaded_ir["nodes"][0]["type"] == ...`, `assert loaded_ir["nodes"][0]["params"] == ...`

This is actually **equivalent or better** than the original — it checks the same semantic content but is more explicit about what fields matter. The change was needed because markdown parse adds/normalizes fields.

**Verdict**: Clean. The new assertions are more explicit.

## Stale .json References

Checked all test files for stale `.json` references. Found only intentional ones:
- `test_workflow_resolution.py`: Tests that `.json` file paths are correctly detected as path-like (4 references in `is_likely_workflow_name` tests) — these are testing backwards-compatibility detection
- `test_validate_only.py`: `test_validate_only_rejects_json_files` — intentionally tests that `.json` files are rejected with a helpful message

No stale/dead `.json` assertions found.

## Clean Files (no concerns)

All files not listed in Concerns above are clean. The changes in these files are strictly:
1. `.json` -> `.pflow.md` string replacements
2. `json.dump()` -> `ir_to_markdown()` / `write_workflow_file()` for test setup
3. File content checks adapted from JSON structure to markdown/YAML frontmatter structure
4. Unicode escape fixes (`"✓"` -> `"\u2713"`)
5. Test assertions properly adapted to check equivalent semantic properties in the new format

## Overall Assessment

The migration is **well-executed**. The vast majority of changes are mechanical format swaps. The few test removals are justified by corresponding production code removals. Two minor weakness patterns were identified:

1. **`assert workflow_ir is not None`** pattern (3 instances in test_workflow_resolution.py) — should be strengthened to check structural properties
2. **Auto-normalization test** in test_workflow_save_cli.py lost verification of the normalization behavior — should add content assertions

Neither of these represents a regression risk — they are "slightly weaker than ideal" rather than "broken or misleading."
