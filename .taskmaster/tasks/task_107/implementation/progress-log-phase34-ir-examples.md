# Fork: Task 107 — Phase 3.4 — Rewrite test_ir_examples.py for .pflow.md format

## Entry 1: Complete rewrite of test_ir_examples.py

Attempting: Replace all JSON-based example tests with markdown-based equivalents.

Result:
- ✅ Removed `json` import, added `parse_markdown`, `MarkdownParseError`, `normalize_ir` imports
- ✅ Updated `test_core_examples_exist`: 5 `.pflow.md` files
- ✅ Updated `test_advanced_examples_exist`: 2 `.pflow.md` files
- ✅ Updated `test_invalid_examples_exist`: 8 new markdown-specific invalid examples
- ✅ Updated `test_valid_examples_pass_validation`: parametrized with 7 `.pflow.md` paths, uses `parse_markdown()` → `normalize_ir()` → `validate_ir()`
- ✅ Replaced `test_documentation_exists_for_examples` (checked for companion .md files) with `test_pflow_md_files_are_self_documenting` (verifies .pflow.md files have titles — they ARE the documentation)
- ✅ Replaced all 4 `TestInvalidExamples` tests (missing-version, duplicate-ids, bad-edge-ref, wrong-types) with 8 markdown-specific tests: missing-steps, missing-type, missing-description, unclosed-fence, bare-code-block, duplicate-param, duplicate-ids, yaml-syntax-error
- ✅ Replaced `test_error_handling_has_action_edges` (checked for error/retry action edges) with `test_error_handling_has_multiple_nodes` (verifies nodes exist — edges are auto-generated from document order, action edges not supported yet)
- ✅ Replaced `test_proxy_mappings_has_mappings` (checked IR `mappings` field) with `test_proxy_mappings_example_parses` (verifies parse + validate — mappings is an IR feature not in markdown)
- ✅ Replaced `test_all_json_files_are_valid_json` with `test_all_pflow_md_files_parse` (recursive parse+validate of all non-invalid examples)
- ✅ Removed `test_template_variables_contains_dollar_syntax` — kept as-is (reads raw text, checks for `${var}`)
- ✅ All 23 tests pass
- ✅ ruff lint and format clean

Files modified: `tests/test_core/test_ir_examples.py`
Status: Complete. All 23 tests pass. No issues for main agent.
