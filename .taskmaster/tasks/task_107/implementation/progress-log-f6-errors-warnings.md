# Fork: Task 107 — Phase 2.7 + 2.8 — Error Messages + Unknown Param Warnings

## Entry 1: Update error messages in ir_schema.py

Attempting: Replace JSON syntax examples with markdown syntax in output suggestion messages and update "Invalid JSON" error text.

Result:
- ✅ `_get_output_suggestion()` Case 1 (additional properties): JSON example replaced with markdown `### story` section format
- ✅ `_get_output_suggestion()` Case 2 (wrong type): JSON wrapping example replaced with markdown section format
- ✅ `validate_ir()` line 481: Changed "Invalid JSON: {e}" to "Invalid workflow data: {e}"
- ✅ Updated `test_ir_schema.py::test_invalid_json_string` assertion from "Invalid JSON" to "Invalid workflow data"
- ✅ Updated `test_ir_schema_output_suggestions.py::test_wrong_type_shows_wrapping` assertion to check for markdown syntax (`- source:` instead of `'"source"'`)

Files modified: `src/pflow/core/ir_schema.py`, `tests/test_core/test_ir_schema.py`, `tests/test_core/test_ir_schema_output_suggestions.py`
Status: Phase 2.7 complete.

## Entry 2: Remove layer 7 and add unknown param warnings

Attempting: Remove JSON string anti-pattern validation (layer 7) from WorkflowValidator and replace with unknown param warning layer.

Result:
- ✅ Removed `_check_json_string_with_template()`, `_build_param_type_map()`, and `_validate_json_string_templates()` methods
- ✅ Removed unused module-level `import re` (local `import re` in `_validate_template_in_source` still used)
- ✅ Added `_validate_unknown_params()` method as new layer 7:
  - Loads interface metadata via `registry.get_nodes_metadata()`
  - Extracts known param keys from `interface["params"]` and `interface["inputs"]`
  - Compares node params against known keys
  - Uses `find_similar_items()` from `suggestion_utils.py` for "Did you mean?" suggestions
  - Returns warnings (not errors) — unknown params don't break execution
  - Skips nodes with unknown types or no interface metadata
- ✅ Updated `validate()` docstring to reference "Unknown param warnings" instead of "JSON string template validation"
- ✅ Updated layer 7 call in `validate()` to use `_validate_unknown_params()` and append to `warnings` (not `errors`)
- ✅ Replaced test file `test_json_string_template_validation.py` with unknown param warning tests (9 tests)
- ✅ All 81 relevant tests pass (12 validator, 57 ir_schema, 3 output suggestions, 9 unknown param warnings)

Files modified:
- `src/pflow/core/workflow_validator.py`
- `tests/test_core/test_json_string_template_validation.py` (rewritten for unknown param warnings)

Status: Phase 2.8 complete.

## Final Status

All assigned work complete:
- `src/pflow/core/ir_schema.py` — JSON examples replaced with markdown syntax, error message updated
- `src/pflow/core/workflow_validator.py` — Layer 7 removed (JSON anti-pattern), replaced with unknown param warning layer
- `tests/test_core/test_ir_schema.py` — Updated assertion for new error message
- `tests/test_core/test_ir_schema_output_suggestions.py` — Updated assertion for markdown syntax
- `tests/test_core/test_json_string_template_validation.py` — Rewritten with 9 unknown param warning tests

Quality checks on assigned files:
- ✅ 81/81 tests pass
- ✅ No ruff or mypy issues in modified files

Note for main agent: The `test_core/test_stdin_no_hang.py` test fails because F1 (CLI fork) has already added .json rejection — this is expected concurrent fork behavior, not related to my changes.

Fork F6 complete.
