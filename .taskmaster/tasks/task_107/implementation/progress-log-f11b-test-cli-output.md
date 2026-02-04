# Fork: Task 107 — Phase 3.3 — Fix CLI output/display/validation test files (F11b)

## Entry 1: Fix all 5 test files

Attempting: Replace JSON workflow file writing with .pflow.md in 5 CLI test files.

Result:
- ✅ test_shell_stderr_warnings.py: 16/16 passed — replaced json.dumps with write_workflow_file, changed .json to .pflow.md. Needed to keep json import for json.loads() in JSON output parsing tests.
- ✅ test_enhanced_error_output.py: 9/9 passed — same pattern: import write_workflow_file, replace json.dumps, change .json to .pflow.md.
- ✅ test_workflow_output_source_simple.py: 5/5 passed — uses tempfile.NamedTemporaryFile, changed suffix from .json to .pflow.md, replaced json.dump with ir_to_markdown().
- ✅ test_validation_before_execution.py: 5/5 passed — same pattern with write_workflow_file.
- ✅ test_shell_stderr_display.py: 4/4 passed — same pattern with write_workflow_file.

Changes per file were mechanical:
1. Added import from tests.shared.markdown_utils
2. Changed file extensions from .json to .pflow.md
3. Replaced json.dumps/json.dump with write_workflow_file or ir_to_markdown
4. Kept json import where json.loads is used for parsing CLI JSON output

Files modified:
- tests/test_cli/test_shell_stderr_warnings.py
- tests/test_cli/test_enhanced_error_output.py
- tests/test_cli/test_workflow_output_source_simple.py
- tests/test_cli/test_validation_before_execution.py
- tests/test_cli/test_shell_stderr_display.py

Status: All 5 files complete. 39 tests total, all passing. Fork F11b done.
