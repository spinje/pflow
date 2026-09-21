# Template Validation Tests

Tests for `src/pflow/runtime/template_validation/`. Use `tests/shared/diagnostic_helpers.py::split_template_diagnostics` to call `validate_workflow_templates` and split typed `Diagnostic` results by severity. `test_type_checker.py` exercises helpers directly; `test_array_notation.py` and `test_validator.py` also test `_extract_all_templates`.

## Source-to-Test Mapping

Test filenames are local; source modules are under `src/pflow/runtime/template_validation/`.

| Test file | Source module | What it covers |
|-----------|-------------|----------------|
| `test_validator.py` | `validator.py` | Orchestrator, template extraction, batch-through-orchestrator integration |
| `test_batch_item_validation.py` | `batch_item_validation.py` | `${item.field}` validation against inferred item structure |
| `test_types.py` | `type_validation.py` | Parameter type matching, shell command safety, code-node input annotations |
| `test_union_types.py` | `type_validation.py` | Union type handling (`dict\|str`) in type matching |
| `test_type_checker.py` | `type_checker.py` | Type compatibility matrix, type inference |
| `test_enhanced_errors.py` | `path_validation.py` | Error messages with input descriptions |
| `test_malformed.py` | `validator.py` | Malformed template syntax detection (`${`, `${}`) |
| `test_unused_inputs.py` | `validator.py` | Unused declared input detection |
| `test_warnings.py` | `path_validation.py` | Runtime validation warnings (str type + nested access) |
| `test_array_notation.py` | `validator.py` | Array notation in templates (`${node[0].field}`) |
| `test_literal_operands.py` | `validator.py` | Literal operands in `??` and bare literals (`${a ?? 0}`, `${0}`) |

## Mock Pattern

Registry setup is local to each test concern: several files define `create_mock_registry()`, `test_unused_inputs.py` defines `MockRegistry`, and `test_types.py` uses a temporary real registry. Preserve the scenario-specific node/output metadata when changing or consolidating fixtures.
