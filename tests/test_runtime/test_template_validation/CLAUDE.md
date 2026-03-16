# Template Validation Tests

Tests for `src/pflow/runtime/template_validation/`. All tests call through the public API (`validate_workflow_templates`) unless noted.

## Source-to-Test Mapping

| Test file | Source module | What it covers |
|-----------|-------------|----------------|
| `test_validator.py` | `validator.py` | Orchestrator, template extraction, batch-through-orchestrator integration |
| `test_batch_item_validation.py` | `batch_item_validation.py` | `${item.field}` validation against inferred item structure |
| `test_types.py` | `type_validation.py` | Pass 6 (type matching) + Pass 7 (shell command safety) |
| `test_union_types.py` | `type_validation.py` | Union type handling (`dict\|str`) in type matching |
| `test_type_checker.py` | `type_checker.py` | Type compatibility matrix, type inference |
| `test_enhanced_errors.py` | `path_validation.py` | Error messages with input descriptions |
| `test_malformed.py` | `validator.py` | Malformed template syntax detection (`${`, `${}`) |
| `test_unused_inputs.py` | `validator.py` | Unused declared input detection |
| `test_warnings.py` | `path_validation.py` | Runtime validation warnings (str type + nested access) |
| `test_array_notation.py` | `validator.py` | Array notation in templates (`${node[0].field}`) |

## Mock Pattern

Most files define their own `create_mock_registry()` with node metadata specific to that file's tests. This is intentional — each registry has different nodes/outputs needed for its scenarios. Don't extract to conftest.
