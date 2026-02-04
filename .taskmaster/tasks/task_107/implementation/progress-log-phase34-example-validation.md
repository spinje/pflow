# Fork: Task 107 — Phase 3.4 — Fix test_example_validation.py for markdown format

## Entry 1: Rewrite test_example_validation.py for .pflow.md format

Attempting: Complete rewrite of the test file to scan for .pflow.md files instead of .json, use parse_markdown() instead of json.load(), and handle both parse errors and validation errors for invalid examples.

Result:
- ✅ Removed json import, extract_ir() helper (no longer needed — parse_markdown returns .ir directly)
- ✅ Added imports: parse_markdown, MarkdownParseError, normalize_ir
- ✅ valid_workflow_files fixture: scans *.pflow.md, parses with parse_markdown(), normalizes with normalize_ir()
- ✅ invalid_workflow_files fixture: simplified to return list of Path objects (just scans examples/invalid/*.pflow.md)
- ✅ test_invalid_examples_fail_parsing_or_validation: catches both MarkdownParseError and ValidationError
- ✅ test_example_coverage_is_meaningful: kept >= 10 assertion (28 valid files found)
- ✅ Removed test_invalid_examples_fail_schema_validation (replaced with parsing_or_validation variant)
- ✅ All 3 tests pass
- ✅ ruff check clean, ruff format clean

Files modified: `tests/test_docs/test_example_validation.py`
Status: Assignment complete. All tests pass, linting clean.
