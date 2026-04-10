# Task 151: Split core/diagnostic.py — Separate Data Model from Rendering

## Description

Split `core/diagnostic.py` (870 lines) into two files: a ~130-line data model (`diagnostic.py`) and a ~740-line rendering module (`diagnostic_render.py`). This is the highest-leverage structural refactor in the codebase — `diagnostic.py` is the #1 most-imported file (25+ consumers across every layer), but ~18 of those consumers only need the data model and currently load 870 lines of rendering code they never use.

## Status

not started

## Priority

high

## Problem

`core/diagnostic.py` grew through four sequential tasks (143, 144, 147, 148) that each legitimately added rendering complexity. The data model (`Diagnostic`, `Severity`) stabilized at Task 143 and has barely changed. The rendering section grew 5x since then and is now 76% of the file (661 lines).

Concrete costs:
- **Context window waste**: ~18 consumers (runtime/, core/workflow/, execution/result.py, mcp/errors.py) load 870 lines but only need ~120 lines of data model
- **Agent navigability**: An agent opening diagnostic.py to understand the `Diagnostic` type must scan past 660 lines of rendering helpers to orient themselves
- **Change coupling**: Rendering improvements (new error categories, format tweaks) and data model changes (new fields on Diagnostic) are unrelated concerns that currently share a file
- **Rate of change mismatch**: The rendering section will keep growing as more failure categories and error types are added; the data model is stable

## Solution

Split into two files within `core/`:

```
core/
├── diagnostic.py           # Data model (~130 lines)
│   Severity, Diagnostic, deduplicate_diagnostics,
│   format_child_provenance, _CATEGORY_TITLES
│
└── diagnostic_render.py    # Rendering + exception conversion (~740 lines)
    format_diagnostic, exception_to_diagnostics,
    _format_error_diagnostic, _format_warning_or_info_diagnostic,
    _format_template_error_lines, _format_one_reference,
    _render_failure_data_block, _builtin_exception_diagnostic,
    + all other _format_* / _render_* helpers
```

## Design Decisions

- **`_CATEGORY_TITLES` stays in `diagnostic.py`**: `executor_service.py` imports it for error categorization (not rendering). It's a data lookup dict, not a rendering function. Keeping it with the data model avoids forcing a rendering import for non-rendering use.

- **`format_child_provenance` stays in `diagnostic.py`**: It's identity-critical (dedup invariant documented in the function docstring) and used by both the validation path (`core/workflow/validator.py`) and the runtime path (`runtime/workflow_executor.py`) — neither of which needs rendering. Moving it to `diagnostic_render.py` would force those files to import the renderer.

- **`exception_to_diagnostics` moves to `diagnostic_render.py`**: It's a conversion/dispatch function used exclusively by display-layer code (CLI error_output, workflow_output, formatters, visualize command). It also has lazy imports of `security_utils` for the same reason the renderers do. It belongs with the rendering pipeline.

- **No re-exports from `diagnostic.py` for rendering symbols**: Clean break. Consumers that need rendering functions import from `diagnostic_render.py` directly. No backward-compat shims — we have zero users and the import changes are mechanical.

- **Single split, not three files**: A three-way split (data model / rendering / exception conversion) was considered but `exception_to_diagnostics` is tightly coupled with the rendering pipeline (both import `security_utils`, both serve the display layer). Two files is the right granularity.

## Dependencies

None. This is a pure structural refactor with no logic changes.

## Requirements

### Split Boundary

- `diagnostic.py` contains ONLY: `Severity`, `Diagnostic`, `deduplicate_diagnostics`, `format_child_provenance`, `_CATEGORY_TITLES`
- `diagnostic_render.py` contains: `format_diagnostic`, `exception_to_diagnostics`, `_builtin_exception_diagnostic`, and ALL `_format_*` / `_render_*` private helpers
- `diagnostic_render.py` imports `Severity`, `Diagnostic` from `diagnostic.py` — dependency flows one way (render → model), never the reverse
- No circular imports between the two files

### Consumer Updates

- All production imports across `src/pflow/` updated to the correct module
- All test imports updated
- All `mock.patch()` string targets updated (these are runtime failures, not caught by import checks)
- No import of rendering symbols from `diagnostic.py` (clean break, no re-exports)

### Zero Behavior Change

- No logic changes — code moves between files, nothing else
- No renaming of functions, classes, or constants
- No addition or removal of docstrings, comments, or type annotations
- `make test` pass count matches baseline exactly
- `make check` passes clean (may need two runs for ruff import reordering)

### Documentation

- `core/CLAUDE.md` updated: diagnostic.py entry split into two entries describing each file's contents
- Any other CLAUDE.md files that reference `diagnostic.py` updated to mention both files where appropriate

## Implementation Notes

### Consumer import patterns (from assessment)

**Data-model-only consumers (~18 files, NO import changes needed):**
These import `Diagnostic`, `Severity`, `deduplicate_diagnostics`, `format_child_provenance`, or `_CATEGORY_TITLES` — all of which stay in `diagnostic.py`:
- `runtime/engine/template_errors.py`, `template_resolution.py`
- `runtime/workflow_trace.py`, `workflow_executor.py`
- `runtime/template_validation/` (multiple files)
- `core/exceptions.py`, `core/workflow/validator.py`, `core/workflow/data_flow.py`, `core/workflow/save_service.py`
- `execution/result.py`, `execution/executor_service.py`
- `mcp/errors.py`

**Rendering consumers (~9 files, need import path change):**
These import `format_diagnostic`, `exception_to_diagnostics`, or both:
- `cli/error_output.py`
- `cli/workflow_output.py`
- `cli/commands/registry_run.py`
- `cli/commands/mcp.py`
- `cli/commands/visualize.py`
- `execution/formatters/success_formatter.py`
- `execution/formatters/validation_formatter.py`
- `execution/formatters/registry_error_helpers.py`
- `cli/workflow_errors.py` (if it imports rendering symbols)

### mock.patch sweep

Run before implementation:
```bash
grep -rn "mock.patch.*diagnostic" tests/ --include="*.py"
grep -rn "patch(\"pflow.core.diagnostic" tests/ --include="*.py"
grep -rn "patch('pflow.core.diagnostic" tests/ --include="*.py"
```
Every string target referencing a function that moves to `diagnostic_render.py` must be updated.

### Internal call graph

`diagnostic_render.py` will have this internal structure:
- `format_diagnostic()` dispatches to `_format_error_diagnostic` or `_format_warning_or_info_diagnostic`
- `_format_error_diagnostic` calls `_format_location`, `_format_all_context_blocks`, renders suggestions
- `_format_all_context_blocks` dispatches to `_format_compilation_context_lines`, `_format_similar_names_block`, `_format_exception_type_line`, `_format_available_fields_block`, `_format_template_error_lines`, `_format_shell_error_lines`, `_format_api_response_lines`, `_format_mcp_error_lines`
- `_format_template_error_lines` calls `_format_output_block`, `_format_all_unavailable_coalesce_summary`, `_format_context_keys_block`
- `_format_one_reference` dispatches to `_format_absent_reference`, `_format_failed_reference`, `_format_path_error_reference`
- `_render_failure_data_block` dispatches to `_render_shell_failure_block`, `_render_http_failure_block`, `_render_mcp_failure_block`, `_render_generic_failure_block`
- `exception_to_diagnostics` calls `_builtin_exception_diagnostic`

All internal. No cross-file calls back to `diagnostic.py` beyond importing `Diagnostic` and `Severity`.

### Lazy imports in diagnostic_render.py

`_format_api_response_lines` and `_format_mcp_error_lines` have lazy imports of `pflow.core.security_utils.sanitize_parameters`. These stay as-is (they're lazy to avoid import-time cost, not circular dependency).

`exception_to_diagnostics` has a lazy `from dataclasses import replace`. This also stays as-is.

## Verification

- `make test` — pass count matches pre-refactor baseline exactly
- `make check` — ruff + mypy + deptry pass clean
- Zero references to old paths: `grep -rn "from pflow.core.diagnostic import.*format_diagnostic\|exception_to_diagnostics" src/ tests/` returns only `diagnostic_render.py` imports
- Every `mock.patch` string targeting moved functions updated: `grep -rn "pflow.core.diagnostic\." tests/` shows no references to moved symbols at the old path
- Stale reference sweep across CLAUDE.md files and architecture docs
- No new files created beyond `diagnostic_render.py`
- No files deleted

## References

- Current file: `src/pflow/core/diagnostic.py` (870 lines)
- CLAUDE.md with documented structure: `src/pflow/core/CLAUDE.md`
- Task 143 (created Diagnostic type): `.taskmaster/tasks/task_143/`
- Task 144 (display consolidation, added polymorphic rendering): `.taskmaster/tasks/task_144/`
- Task 147 (validator produces diagnostics, added template error rendering): `.taskmaster/tasks/task_147/`
- Task 148 (failed-node invariant, added failure-category rendering): `.taskmaster/tasks/task_148/`
- Assessment scratchpad with full consumer analysis: this conversation's Phase 0 assessment
